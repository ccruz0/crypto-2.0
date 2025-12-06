"""
Canonical signal evaluation helper.

This module provides a single source of truth for signal evaluation logic,
ensuring that both the live SignalMonitorService and debug scripts use
EXACTLY the same logic to compute BUY/SELL signals, throttle status, and flags.
"""
from typing import Dict, List, Optional, Any
try:
    from typing import TypedDict, Literal
except ImportError:
    # Python < 3.8 fallback
    TypedDict = dict
    Literal = str
from datetime import datetime, timezone
from sqlalchemy.orm import Session
import logging

from app.models.watchlist import WatchlistItem
from app.models.market_price import MarketPrice, MarketData
from app.services.trading_signals import calculate_trading_signals
from app.services.strategy_profiles import resolve_strategy_profile, StrategyType, RiskApproach
from app.services.signal_throttle import (
    SignalThrottleConfig,
    build_strategy_key,
    fetch_signal_states,
    should_emit_signal,
)
from app.services.config_loader import get_alert_thresholds
from price_fetcher import get_price_with_fallback

logger = logging.getLogger(__name__)


class SignalEvalResult(TypedDict):
    """Structured result from signal evaluation."""
    decision: Literal["BUY", "SELL", "WAIT"]
    buy_signal: bool
    sell_signal: bool
    index: Optional[int]
    buy_allowed: bool
    sell_allowed: bool
    buy_flag_allowed: bool
    sell_flag_allowed: bool
    can_emit_buy_alert: bool
    can_emit_sell_alert: bool
    throttle_status_buy: str  # SENT / BLOCKED / N/A
    throttle_status_sell: str  # SENT / BLOCKED / N/A
    throttle_reason_buy: str
    throttle_reason_sell: str
    missing_indicators: List[str]
    debug_flags: Dict[str, Any]  # buy_rsi_ok, sell_volume_ok, etc.
    price: float
    rsi: Optional[float]
    ma50: Optional[float]
    ma200: Optional[float]
    ema10: Optional[float]
    volume_ratio: Optional[float]
    min_volume_ratio: float
    strategy_key: str
    preset: str
    error: Optional[str]


def evaluate_signal_for_symbol(
    db: Session,
    watchlist_item: WatchlistItem,
    symbol: str,
) -> SignalEvalResult:
    """
    Canonical signal evaluation for a single symbol.
    
    This function encapsulates the EXACT logic used by debug_live_signals_all.py
    to ensure the live monitor uses identical evaluation.
    
    Args:
        db: Database session
        watchlist_item: WatchlistItem for the symbol
        symbol: Trading symbol to evaluate
        
    Returns:
        SignalEvalResult with all evaluation details
    """
    result: SignalEvalResult = {
        "decision": "WAIT",
        "buy_signal": False,
        "sell_signal": False,
        "index": None,
        "buy_allowed": False,
        "sell_allowed": False,
        "buy_flag_allowed": False,
        "sell_flag_allowed": False,
        "can_emit_buy_alert": False,
        "can_emit_sell_alert": False,
        "throttle_status_buy": "N/A",
        "throttle_status_sell": "N/A",
        "throttle_reason_buy": "",
        "throttle_reason_sell": "",
        "missing_indicators": [],
        "debug_flags": {},
        "price": 0.0,
        "rsi": None,
        "ma50": None,
        "ma200": None,
        "ema10": None,
        "volume_ratio": None,
        "min_volume_ratio": 0.5,
        "strategy_key": "",
        "preset": "",
        "error": None,
    }
    
    try:
        # Resolve strategy profile (same as debug script)
        strategy_type, risk_approach = resolve_strategy_profile(symbol, db, watchlist_item)
        strategy_key = build_strategy_key(strategy_type, risk_approach)
        preset_name = strategy_type.value.lower()
        risk_mode = risk_approach.value.capitalize()
        preset = f"{preset_name}-{risk_mode}"
        
        result["strategy_key"] = strategy_key
        result["preset"] = preset
        
        # Get throttle config (same as debug script)
        min_price_change_pct = getattr(watchlist_item, "min_price_change_pct", None)
        alert_cooldown_minutes = getattr(watchlist_item, "alert_cooldown_minutes", None)
        
        try:
            preset_min, preset_cooldown = get_alert_thresholds(symbol, strategy_key)
            if min_price_change_pct is None:
                min_price_change_pct = preset_min
            if alert_cooldown_minutes is None:
                alert_cooldown_minutes = preset_cooldown
        except Exception:
            pass
        
        if min_price_change_pct is None:
            min_price_change_pct = 1.0
        if alert_cooldown_minutes is None:
            alert_cooldown_minutes = 5.0
        
        throttle_config = SignalThrottleConfig(
            min_price_change_pct=min_price_change_pct,
            min_interval_minutes=alert_cooldown_minutes,
        )
        
        # Get flags (same logic as debug script)
        alert_enabled = bool(getattr(watchlist_item, "alert_enabled", False))
        buy_alert_enabled_raw = getattr(watchlist_item, "buy_alert_enabled", None)
        if alert_enabled and buy_alert_enabled_raw is None:
            buy_enabled = True  # Default to enabled when alert_enabled=True
        else:
            buy_enabled = bool(buy_alert_enabled_raw if buy_alert_enabled_raw is not None else False)
        
        sell_alert_enabled_raw = getattr(watchlist_item, "sell_alert_enabled", None)
        if alert_enabled and sell_alert_enabled_raw is None:
            sell_enabled = True  # Default to enabled when alert_enabled=True
        else:
            sell_enabled = bool(sell_alert_enabled_raw if sell_alert_enabled_raw is not None else False)
        
        result["buy_flag_allowed"] = buy_enabled and alert_enabled
        result["sell_flag_allowed"] = sell_enabled and alert_enabled
        
        # Fetch price and indicators (EXACT same logic as debug script)
        mp = db.query(MarketPrice).filter(MarketPrice.symbol == symbol).first()
        md = db.query(MarketData).filter(MarketData.symbol == symbol).first()
        
        if mp and mp.price and mp.price > 0:
            current_price = mp.price
            volume_24h = mp.volume_24h or 0.0
        else:
            result_api = get_price_with_fallback(symbol, "15m")
            current_price = result_api.get('price', 0)
            volume_24h = result_api.get('volume_24h', 0)
        
        if not current_price or current_price <= 0:
            result["error"] = "No price data"
            return result
        
        result["price"] = current_price
        
        # Get indicators (EXACT same priority as debug script)
        if md and md.rsi is not None:
            rsi = md.rsi
        elif hasattr(watchlist_item, 'rsi') and watchlist_item.rsi is not None:
            rsi = watchlist_item.rsi
        else:
            if 'result_api' not in locals():
                result_api = get_price_with_fallback(symbol, "15m")
            rsi = result_api.get('rsi', None)
        
        result["rsi"] = rsi
        if rsi is None:
            result["missing_indicators"].append("RSI")
        
        if md and md.ma50 is not None:
            ma50 = md.ma50
        elif hasattr(watchlist_item, 'ma50') and watchlist_item.ma50 is not None:
            ma50 = watchlist_item.ma50
        else:
            ma50 = None
        
        result["ma50"] = ma50
        if ma50 is None:
            result["missing_indicators"].append("MA50")
        
        if md and md.ma200 is not None:
            ma200 = md.ma200
        elif hasattr(watchlist_item, 'ma200') and watchlist_item.ma200 is not None:
            ma200 = watchlist_item.ma200
        else:
            ma200 = current_price
        
        result["ma200"] = ma200
        
        if md and md.ema10 is not None:
            ema10 = md.ema10
        elif hasattr(watchlist_item, 'ema10') and watchlist_item.ema10 is not None:
            ema10 = watchlist_item.ema10
        else:
            ema10 = None
        
        result["ema10"] = ema10
        if ema10 is None:
            result["missing_indicators"].append("EMA10")
        
        if md and md.atr is not None:
            atr = md.atr
        elif hasattr(watchlist_item, 'atr') and watchlist_item.atr is not None:
            atr = watchlist_item.atr
        else:
            atr = current_price * 0.02
        
        if md and md.ma10w is not None and md.ma10w > 0:
            ma10w = md.ma10w
        elif ma200 and ma200 > 0:
            ma10w = ma200
        elif ma50 and ma50 > 0:
            ma10w = ma50
        else:
            ma10w = current_price
        
        # Get volume data (EXACT same logic as debug script)
        if md and md.current_volume is not None and md.current_volume > 0:
            current_volume = md.current_volume
        elif volume_24h > 0:
            current_volume = volume_24h / 24.0
        else:
            current_volume = None
        
        if md and md.avg_volume is not None and md.avg_volume > 0:
            avg_volume = md.avg_volume
        else:
            avg_volume = (volume_24h / 24.0) if volume_24h > 0 else None
        
        if current_volume and avg_volume and avg_volume > 0:
            volume_ratio = current_volume / avg_volume
            result["volume_ratio"] = volume_ratio
        
        # Get min_volume_ratio from strategy config
        from app.services.config_loader import get_strategy_rules
        strategy_rules = get_strategy_rules(preset_name, risk_mode, symbol=symbol)
        min_volume_ratio = strategy_rules.get("volumeMinRatio", 0.5)
        result["min_volume_ratio"] = min_volume_ratio
        
        # Calculate resistance levels
        price_precision = 2 if current_price >= 100 else 4
        res_up = round(current_price * 1.02, price_precision)
        res_down = round(current_price * 0.98, price_precision)
        
        # Calculate trading signals (EXACT same call as debug script)
        signals = calculate_trading_signals(
            symbol=symbol,
            price=current_price,
            rsi=rsi,
            atr14=atr,
            ma50=ma50,
            ma200=ma200,
            ema10=ema10,
            ma10w=ma10w,
            volume=current_volume,
            avg_volume=avg_volume,
            resistance_up=res_up,
            buy_target=watchlist_item.buy_target,
            last_buy_price=watchlist_item.purchase_price if watchlist_item.purchase_price and watchlist_item.purchase_price > 0 else None,
            position_size_usd=watchlist_item.trade_amount_usd if watchlist_item.trade_amount_usd and watchlist_item.trade_amount_usd > 0 else 100.0,
            rsi_buy_threshold=40,
            rsi_sell_threshold=70,
            strategy_type=strategy_type,
            risk_approach=risk_approach,
        )
        
        buy_signal = signals.get("buy_signal", False)
        sell_signal = signals.get("sell_signal", False)
        strategy_state = signals.get("strategy_state", {})
        
        # Determine decision (EXACT same logic as debug script)
        if buy_signal:
            actual_decision = "BUY"
        elif sell_signal:
            actual_decision = "SELL"
        else:
            actual_decision = "WAIT"
        
        result["decision"] = actual_decision
        result["buy_signal"] = buy_signal
        result["sell_signal"] = sell_signal
        result["index"] = strategy_state.get("index")
        
        # Extract debug flags from strategy_state
        reasons = strategy_state.get("reasons", {})
        result["debug_flags"] = {
            "buy_rsi_ok": reasons.get("buy_rsi_ok"),
            "buy_ma_ok": reasons.get("buy_ma_ok"),
            "buy_volume_ok": reasons.get("buy_volume_ok"),
            "buy_target_ok": reasons.get("buy_target_ok"),
            "buy_price_ok": reasons.get("buy_price_ok"),
            "sell_rsi_ok": reasons.get("sell_rsi_ok"),
            "sell_trend_ok": reasons.get("sell_trend_ok"),
            "sell_volume_ok": reasons.get("sell_volume_ok"),
        }
        
        # Check throttle for BUY (EXACT same logic as debug script)
        if buy_signal:
            signal_snapshots = fetch_signal_states(db, symbol=symbol, strategy_key=strategy_key)
            now_utc = datetime.now(timezone.utc)
            buy_allowed, buy_reason = should_emit_signal(
                symbol=symbol,
                side="BUY",
                current_price=current_price,
                current_time=now_utc,
                config=throttle_config,
                last_same_side=signal_snapshots.get("BUY"),
                last_opposite_side=signal_snapshots.get("SELL"),
            )
            result["buy_allowed"] = buy_allowed
            result["throttle_status_buy"] = "SENT" if buy_allowed else "BLOCKED"
            result["throttle_reason_buy"] = buy_reason if not buy_allowed else ""
            result["can_emit_buy_alert"] = buy_allowed and buy_enabled
        else:
            result["buy_allowed"] = False
            result["throttle_status_buy"] = "N/A"
            result["throttle_reason_buy"] = ""
            result["can_emit_buy_alert"] = False
        
        # Check throttle for SELL (EXACT same logic as debug script)
        if sell_signal:
            signal_snapshots = fetch_signal_states(db, symbol=symbol, strategy_key=strategy_key)
            now_utc = datetime.now(timezone.utc)
            sell_allowed, sell_reason = should_emit_signal(
                symbol=symbol,
                side="SELL",
                current_price=current_price,
                current_time=now_utc,
                config=throttle_config,
                last_same_side=signal_snapshots.get("SELL"),
                last_opposite_side=signal_snapshots.get("BUY"),
            )
            result["sell_allowed"] = sell_allowed
            result["throttle_status_sell"] = "SENT" if sell_allowed else "BLOCKED"
            result["throttle_reason_sell"] = sell_reason if not sell_allowed else ""
            result["can_emit_sell_alert"] = sell_allowed and sell_enabled
        else:
            result["sell_allowed"] = False
            result["throttle_status_sell"] = "N/A"
            result["throttle_reason_sell"] = ""
            result["can_emit_sell_alert"] = False
        
    except Exception as e:
        logger.error(f"Error evaluating {symbol}: {e}", exc_info=True)
        result["error"] = str(e)[:50]
    
    return result

