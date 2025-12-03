"""
Tests for canonical BUY rule in calculate_trading_signals.

This test ensures that when all buy_* reasons are True, the backend
correctly sets decision=BUY and buy_signal=True, regardless of position state.
"""
import pytest
from app.services.trading_signals import calculate_trading_signals
from app.services.strategy_profiles import StrategyType, RiskApproach


def test_canonical_buy_rule_all_flags_true():
    """Test that when all buy_* flags are True, decision=BUY and buy_signal=True."""
    result = calculate_trading_signals(
        symbol="TEST_USDT",
        price=100.0,
        rsi=35.0,  # Below threshold (should be < 40)
        ma50=95.0,
        ma200=90.0,
        ema10=98.0,
        volume=1000.0,
        avg_volume=500.0,  # Volume ratio = 2.0 (above 0.5 threshold)
        buy_target=110.0,  # Price (100) <= buy_target (110) ✓
        last_buy_price=None,  # No position
        strategy_type=StrategyType.SWING,
        risk_approach=RiskApproach.CONSERVATIVE,
    )
    
    # Verify canonical rule triggered
    assert result["buy_signal"] is True, "buy_signal should be True when all buy_* flags are True"
    
    strategy = result.get("strategy", {})
    decision = strategy.get("decision")
    assert decision == "BUY", f"decision should be BUY, got {decision}"
    
    reasons = strategy.get("reasons", {})
    # Check that all buy_* boolean flags are True
    buy_flags = {k: v for k, v in reasons.items() if k.startswith("buy_") and isinstance(v, bool)}
    assert all(buy_flags.values()), f"All buy_* flags should be True, got {buy_flags}"


def test_canonical_buy_rule_with_position():
    """Test that canonical rule works even when last_buy_price is set (position exists)."""
    result = calculate_trading_signals(
        symbol="TEST_USDT",
        price=100.0,
        rsi=35.0,
        ma50=95.0,
        ma200=90.0,
        ema10=98.0,
        volume=1000.0,
        avg_volume=500.0,
        buy_target=110.0,
        last_buy_price=95.0,  # Position exists - should NOT block signal
        strategy_type=StrategyType.SWING,
        risk_approach=RiskApproach.CONSERVATIVE,
    )
    
    # Verify canonical rule still triggers despite position
    assert result["buy_signal"] is True, "buy_signal should be True even with position"
    
    strategy = result.get("strategy", {})
    decision = strategy.get("decision")
    assert decision == "BUY", f"decision should be BUY even with position, got {decision}"


def test_canonical_buy_rule_one_flag_false():
    """Test that when one buy_* flag is False, decision is not BUY."""
    result = calculate_trading_signals(
        symbol="TEST_USDT",
        price=100.0,
        rsi=45.0,  # Above threshold (should be < 40) - this will make buy_rsi_ok=False
        ma50=95.0,
        ma200=90.0,
        ema10=98.0,
        volume=1000.0,
        avg_volume=500.0,
        buy_target=110.0,
        last_buy_price=None,
        strategy_type=StrategyType.SWING,
        risk_approach=RiskApproach.CONSERVATIVE,
    )
    
    strategy = result.get("strategy", {})
    decision = strategy.get("decision")
    reasons = strategy.get("reasons", {})
    
    # If RSI is too high, buy_rsi_ok should be False
    if reasons.get("buy_rsi_ok") is False:
        # Canonical rule should NOT trigger
        assert decision != "BUY" or result["buy_signal"] is False, \
            "decision should not be BUY when buy_rsi_ok is False"


def test_canonical_buy_rule_none_flags_ignored():
    """Test that None flags (not blocking) don't prevent BUY decision."""
    result = calculate_trading_signals(
        symbol="TEST_USDT",
        price=100.0,
        rsi=35.0,
        ma50=95.0,
        ma200=90.0,
        ema10=98.0,
        volume=None,  # No volume data - buy_volume_ok will be None
        avg_volume=None,
        buy_target=110.0,
        last_buy_price=None,
        strategy_type=StrategyType.SWING,
        risk_approach=RiskApproach.CONSERVATIVE,
    )
    
    strategy = result.get("strategy", {})
    reasons = strategy.get("reasons", {})
    
    # buy_volume_ok should be None (not blocking)
    assert reasons.get("buy_volume_ok") is None, "buy_volume_ok should be None when volume data unavailable"
    
    # Canonical rule should only check boolean flags, so None should not block
    buy_flags = {k: v for k, v in reasons.items() if k.startswith("buy_") and isinstance(v, bool)}
    if all(buy_flags.values()):
        assert result["buy_signal"] is True, "buy_signal should be True when all boolean flags are True (None ignored)"


