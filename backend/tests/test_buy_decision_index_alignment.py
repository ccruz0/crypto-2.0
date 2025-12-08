"""
Regression test: Ensure BUY decision and index are aligned.

When all buy_* flags are True:
- decision must be "BUY"
- buy_signal must be True
- index must be 100 (or very close)

This test simulates ALGO_USDT's scenario: scalp-aggressive preset with
RSI < 55, volume ratio >= 0.5, no MA requirement.
"""
import pytest
from app.services.trading_signals import calculate_trading_signals
from app.services.strategy_profiles import StrategyType, RiskApproach


def test_buy_decision_index_alignment_scalp_aggressive():
    """Test that BUY decision and index=100 align for scalp-aggressive preset."""
    symbol = "ALGO_USDT"
    
    # Market state matching ALGO's current situation:
    # - RSI < 55 (scalp-aggressive threshold)
    # - Volume ratio >= 0.5 (meets minimum)
    # - No MA requirement for scalp-aggressive
    # - Price under resistance (buy_target_ok = True)
    # - Price valid (buy_price_ok = True)
    
    signals = calculate_trading_signals(
        symbol=symbol,
        price=0.1428,
        rsi=35.0,  # Below 55 threshold for scalp-aggressive
        atr14=0.001,
        ma50=None,  # Not required for scalp-aggressive
        ma200=None,  # Not required
        ema10=None,  # Not required
        ma10w=None,
        volume=1000.0,  # Current volume
        avg_volume=500.0,  # Average volume (ratio = 2.0x >= 0.5)
        resistance_up=0.1500,  # Above current price
        buy_target=0.1450,  # Above current price (buy_target_ok = True)
        last_buy_price=None,  # No position
        position_size_usd=100.0,
        rsi_buy_threshold=40,
        rsi_sell_threshold=70,
        strategy_type=StrategyType.SCALP,
        risk_approach=RiskApproach.AGGRESSIVE,
    )
    
    strategy = signals.get("strategy", {})
    decision = strategy.get("decision")
    index = strategy.get("index")
    buy_signal = signals.get("buy_signal")
    reasons = strategy.get("reasons", {})
    
    # Assertions
    assert decision == "BUY", f"Expected decision=BUY, got {decision}. Reasons: {reasons}"
    assert buy_signal is True, f"Expected buy_signal=True, got {buy_signal}"
    assert index == 100, f"Expected index=100 when all buy_* flags are True, got {index}. Reasons: {reasons}"
    
    # Verify all buy_* flags are True (or None for non-applicable)
    buy_rsi_ok = reasons.get("buy_rsi_ok")
    buy_volume_ok = reasons.get("buy_volume_ok")
    buy_ma_ok = reasons.get("buy_ma_ok")
    buy_target_ok = reasons.get("buy_target_ok")
    buy_price_ok = reasons.get("buy_price_ok")
    
    # For scalp-aggressive, MA is not required (can be None or True)
    assert buy_rsi_ok is True, f"buy_rsi_ok should be True (RSI=35 < 55), got {buy_rsi_ok}"
    assert buy_volume_ok is True, f"buy_volume_ok should be True (ratio=2.0 >= 0.5), got {buy_volume_ok}"
    assert buy_ma_ok in (True, None), f"buy_ma_ok should be True or None (not required), got {buy_ma_ok}"
    assert buy_target_ok is True, f"buy_target_ok should be True (price < buy_target), got {buy_target_ok}"
    assert buy_price_ok is True, f"buy_price_ok should be True (price valid), got {buy_price_ok}"


def test_buy_decision_index_partial_flags():
    """Test that index reflects partial flag satisfaction."""
    symbol = "TEST_USDT"
    
    # Market state with some flags False:
    # - RSI > threshold (buy_rsi_ok = False)
    # - Volume ratio OK (buy_volume_ok = True)
    # - MA OK (buy_ma_ok = True)
    
    signals = calculate_trading_signals(
        symbol=symbol,
        price=100.0,
        rsi=60.0,  # Above threshold (buy_rsi_ok = False)
        atr14=2.0,
        ma50=95.0,  # Price > MA50
        ma200=90.0,  # Price > MA200
        ema10=98.0,  # MA50 > EMA10
        ma10w=90.0,
        volume=1000.0,
        avg_volume=500.0,  # Ratio = 2.0x (buy_volume_ok = True)
        resistance_up=105.0,
        buy_target=105.0,  # Price < buy_target (buy_target_ok = True)
        last_buy_price=None,
        position_size_usd=100.0,
        rsi_buy_threshold=40,
        rsi_sell_threshold=70,
        strategy_type=StrategyType.SWING,
        risk_approach=RiskApproach.CONSERVATIVE,
    )
    
    strategy = signals.get("strategy", {})
    decision = strategy.get("decision")
    index = strategy.get("index")
    buy_signal = signals.get("buy_signal")
    reasons = strategy.get("reasons", {})
    
    # With RSI too high, decision should be WAIT
    assert decision == "WAIT", f"Expected decision=WAIT (RSI too high), got {decision}"
    assert buy_signal is False, f"Expected buy_signal=False, got {buy_signal}"
    
    # Index should reflect partial satisfaction (e.g., 4 out of 5 flags = 80%)
    # But exact value depends on which flags are boolean vs None
    assert index is not None, f"Index should be calculated, got {index}"
    assert 0 <= index <= 100, f"Index should be 0-100, got {index}"
    
    # Verify RSI flag is False
    buy_rsi_ok = reasons.get("buy_rsi_ok")
    assert buy_rsi_ok is False, f"buy_rsi_ok should be False (RSI=60 > 40), got {buy_rsi_ok}"












